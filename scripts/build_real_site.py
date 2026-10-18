"""Собрать данные сайта по десяти реальным обезличенным делам.

Диалог на сайте отвечает на вопросы о суммах, требованиях и сторонах,
значит ответы должны идти по правилам системы, а не по написанному
руками тексту. Этот скрипт прогоняет конвейер извлечения по каждому
делу и кладёт результат в site/demo/cases.json.

Модель здесь не вызывается намеренно. Вопросы диалога — о суммах,
требованиях, сторонах и о резолютивной части, а всё это собирается
правилами (app/drafting). Вводная и мотивировочная на десять прогонов
по четыре минуты не влияют на то, что показывает диалог.

Что попадает в файл:

- требования с суммами и источниками (как их увидели правила);
- итог резолютивной части и текст пункта решения;
- замечания проверки по этому пункту;
- как это дело решил суд — для сравнения.

Проверка на остатки персональных данных обязательна: файл уходит на
публичный сайт.

Запуск:
    backend/.venv/Scripts/python.exe scripts/build_real_site.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "scripts"))

from app.agents.draft_agent import DraftResult, SectionDraft  # noqa: E402
from app.agents.evidence_pack import build_evidence_pack  # noqa: E402
from app.config import (  # noqa: E402
    EmbeddingProviderName,
    LLMProviderName,
    Settings,
)
from app.models.entities import CaseDocument  # noqa: E402
from app.drafting.operative import build_operative  # noqa: E402
from app.drafting.requirements import (  # noqa: E402
    extract_budget,
    extract_counter_claims,
    extract_fee_and_costs,
    extract_parties,
    extract_procedure,
    extract_requirements,
)
from app.verification.engine import verify_draft  # noqa: E402

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "build_real_demo", ROOT / "scripts" / "build_real_demo.py"
)
base = importlib.util.module_from_spec(spec)
sys.modules["build_real_demo"] = base
spec.loader.exec_module(base)

REAL_DIR = ROOT / "data" / "demo" / "real"
SITE_OUT = ROOT / "site" / "demo" / "cases.json"


def make_settings(case_dir: Path) -> Settings:
    return Settings(
        app_env="development",
        llm_provider=LLMProviderName.MOCK,
        embedding_provider=EmbeddingProviderName.LOCAL,
        ollama_enabled=True,
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="bge-m3",
        embedding_model="bge-m3",
        storage_dir=case_dir / "storage",
        documents_dir=case_dir / "storage",
        demo_dir=ROOT / "data" / "demo",
        laws_dir=ROOT / "data" / "laws",
        templates_dir=ROOT / "data" / "templates",
    )


def build_pack(case_dir: Path, settings: Settings) -> EvidencePack:
    """Собрать пакет доказательств по делу — как это делает конвейер."""
    manifest = json.loads(
        (case_dir / "manifest.json").read_text(encoding="utf-8")
    )
    documents: list[CaseDocument] = []
    for entry in manifest.get("documents", []):
        path = case_dir / entry["filename"]
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        # Документы нужны как объекты CaseDocument: конвейер читает
        # тип и текст, а не кортеж. Такие же объекты создаёт
        # CaseService при загрузке дела, поэтому путь тот же.
        documents.append(
            CaseDocument(
                filename=entry["filename"],
                document_type=entry.get("document_type", "OTHER"),
                mime_type="text/plain",
                page_count=max(1, len(text) // 1800 + 1),
                text=text,
                sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        )
    return build_evidence_pack(
        manifest.get("case_number", ""),
        manifest.get("court", ""),
        manifest.get("category", ""),
        documents,
        settings=settings,
    )


async def process(case_dir: Path) -> dict[str, Any]:
    settings = make_settings(case_dir)
    settings.ensure_dirs()
    pack = build_pack(case_dir, settings)

    money, others, unrecognised = extract_requirements(pack)
    counters = extract_counter_claims(pack)
    fee, costs = extract_fee_and_costs(pack)
    parties = extract_parties(pack)
    procedure = extract_procedure(pack)
    budget = extract_budget(pack)

    operative = build_operative(
        money,
        others,
        counter_claims=counters,
        fee_paid=fee,
        costs=costs,
        parties=parties,
        procedure=procedure,
        budget=budget,
    )

    # Проверяется именно то, что попадёт в демо: резолютивная часть.
    # Остальные разделы на сайте не показываются, и проверять их здесь
    # нечего — незачем гонять модель на десять дел ради результата,
    # который никто не увидит.
    # Источники собираются из требований: у собранной резолютивной части
    # их списка нет, а для демо важно показать, из каких документов
    # взяты суммы.
    sources: list[str] = []
    for claim in list(money) + list(others):
        if claim.source and claim.source not in sources:
            sources.append(claim.source)

    section = SectionDraft(
        key="operative",
        name="РЕШИЛ",
        text=operative.render(),
        is_mock=False,
        citations=sources,
    )
    report = verify_draft(
        DraftResult(case_number=pack.case_number, provider="rules", sections=[section]),
        pack,
    )

    total = sum(
        float(claim.amount or 0) for claim in money if claim.amount is not None
    )
    return {
        "rules": {
            "claims": [
                {
                    "amount": float(claim.amount or 0),
                    "kopecks": int(claim.kopecks),
                    "basis": claim.basis,
                    "source": claim.source,
                }
                for claim in money
            ],
            "other_claims": [
                {"description": item.description, "basis": item.basis}
                for item in others
            ],
            "counter_claims": [
                {
                    "basis": counter.basis,
                    "outcome": str(counter.outcome.value),
                    "source": counter.source,
                }
                for counter in counters
            ],
            "unrecognised": [str(line) for line in unrecognised],
            "fee_paid": fee,
            "costs": costs,
            "budget": budget,
            "procedure": str(procedure.value),
            "parties": {
                "plaintiff": parties.plaintiff,
                "defendant": parties.defendant,
            },
            "total": total,
            "total_with_fee": total + float(fee or 0),
        },
        "operative_text": operative.render(),
        "sources": sources,
        "gaps": operative.gaps,
        "verification": {
            "status": report.status.value,
            "issues": [
                {
                    "type": issue.type.value,
                    "severity": issue.severity.value,
                    "reason": issue.reason,
                    "section": issue.section,
                }
                for issue in report.issues
            ],
            "unsupported_claims": report.unsupported_claims,
            "claims_checked": report.claims_checked,
        },
    }


def leak_check(payload: dict[str, Any]) -> list[str]:
    """Остались ли персональные данные в том, что уйдёт на сайт."""
    text = json.dumps(payload, ensure_ascii=False)
    leaks: list[str] = []
    for pattern, label in base.LEAK_PATTERNS:
        for match in pattern.finditer(text):
            leaks.append(f"{label}: {match.group(0)[:40]}")
    return leaks


async def main() -> int:
    cases_dir = REAL_DIR / "cases"
    index_path = cases_dir / "index.json"
    if not index_path.exists():
        print("ОШИБКА: нет data/demo/real/cases/index.json")
        print("Сначала: python scripts/build_real_cases.py")
        return 1

    index = json.loads(index_path.read_text(encoding="utf-8"))
    out_cases: list[dict[str, Any]] = []

    for entry in index["cases"]:
        case_dir = cases_dir / entry["slug"]
        try:
            processed = await process(case_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"{entry['slug']}: пропущено, {type(exc).__name__}: {exc}")
            continue

        payload = {
            "slug": entry["slug"],
            "case_number": entry["case_number"],
            "court": entry["court"],
            "category": entry["category"],
            "claim_amount": entry["claim_amount"],
            # Список документов, а не их количество: диалог показывает
            # имена файлов дела.
            "documents_list": [
                {"filename": doc["filename"], "title": doc.get("title", "")}
                for doc in json.loads(
                    (case_dir / "manifest.json").read_text(encoding="utf-8")
                ).get("documents", [])
            ],
            "court_decision_reference": entry["court_decision_reference"],
            **processed,
        }

        leaks = leak_check(payload)
        if leaks:
            print(f"{entry['slug']}: пропущено, остались персональные данные:")
            for leak in leaks[:3]:
                print(f"   - {leak}")
            continue

        out_cases.append(payload)
        rules = payload["rules"]
        print(
            f"{entry['slug']}: требований {len(rules['claims'])}, "
            f"итог {rules['total_with_fee']:.0f}, "
            f"замечаний проверки {len(payload['verification']['issues'])}"
        )

    if not out_cases:
        print("ОШИБКА: ни одно дело не попало в сайт")
        return 1

    SITE_OUT.parent.mkdir(parents=True, exist_ok=True)
    SITE_OUT.write_text(
        json.dumps(
            {
                "source": index["source"],
                "anonymised": index["anonymised"],
                "generated_by": "scripts/build_real_site.py",
                "cases": out_cases,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"дел в сайте: {len(out_cases)}\nфайл: {SITE_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))