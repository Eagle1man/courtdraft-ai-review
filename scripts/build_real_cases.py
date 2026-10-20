"""Собрать несколько обезличенных дел из корпуса реальных решений.

Зачем десять, а не одно: показ ректору. Одно дело — это пример, десять
— видно, что система работает не на подобранном удачном случае.

Отбор идёт по содержанию, а не по порядку в корпусе: нужны дела с
суммами, с возражениями ответчика и с мотивировкой, и желательно разные
по предмету. Двадцать одинаковых дел про задолженность за газ
показывают систему хуже, чем десять разных.

Резолютивная часть суда сохраняется отдельно и в материалы дела НЕ
попадает: её система строит сама. Иначе демо показывало бы пересказ
чужого решения, а не работу системы.

Обезличивание выполняет build_real_demo.anonymize: фамилии, инициалы,
названия организаций, номера дел. Каждое дело проверяется на остатки
персональных данных, и непроверенное дело в указатель не попадает.

Запуск:
    python scripts/build_real_cases.py            # 10 дел
    python scripts/build_real_cases.py --count 5
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / filename
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"не найден скрипт {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = _load("build_real_demo", "build_real_demo.py")

anonymize = base.anonymize
split_decision = base.split_decision
score_candidate = base.score_candidate
load_documents = base.load_documents
find_leaks = base.find_leaks
DOCUMENT_TYPES = base.DOCUMENT_TYPES
REAL_DIR = base.REAL_DIR

#: Предмет спора. Разные значения нужны, чтобы дела не выглядели
#: десятью копиями одного примера.
SUBJECTS: list[tuple[str, str]] = [
    ("жилищно-коммунальн", "споры о ЖКУ"),
    ("за пользование газом", "споры о ЖКУ"),
    ("газоснабжен", "споры о ЖКУ"),
    ("отоплен", "споры о ЖКУ"),
    ("договор поставки", "договор поставки"),
    ("договор подряда", "договор подряда"),
    ("договор купли-продажи", "купля-продажа"),
    ("заём", "займы и кредиты"),
    ("кредитн", "займы и кредиты"),
    ("потребительск", "защита прав потребителей"),
    ("трудовые отношения", "трудовые споры"),
    ("заработной платы", "трудовые споры"),
    ("аренд", "аренда"),
    ("страхован", "страхование"),
    ("наследств", "наследство"),
    ("вред здоровью", "вред здоровью"),
    ("морального вреда", "вред здоровью"),
    ("алименты", "семейные споры"),
    ("определение места жительства", "семейные споры"),
]

#: Сколько дел одного предмета допускается.
SUBJECT_LIMIT = 2


def subject_of(text: str) -> str:
    lowered = text.lower()
    for marker, subject in SUBJECTS:
        if marker in lowered:
            return subject
    return "прочие споры"


def court_of(text: str) -> str:
    # Обрезка шла по первой точке, и инициал судьи резал фамилию:
    # «Синяева И.О.» превращалось в «Синяева И», фамилия уходила в
    # манифест мимо find_leaks. Запятая и перевод строки — границы
    # предложения, точка внутри инициалов — нет. Лимит шире старого
    # (70) — на реальных делах он рвал строку посередине фамилии.
    match = re.search(r"(Мировой судья[^,\n]{0,120})", text)
    if match:
        # Лимит отрезал слово посередине: дальше недописанное слово,
        # которое может оказаться фамилией судьи. Проверить его нельзя —
        # «области Чер» неотличимо от настоящего текста. Неполную строку
        # судью называть нельзя, чем оставлять обрубок.
        if match.end() < len(text) and re.match(r"[А-ЯЁа-яё]", text[match.end()]):
            return "Суд (обезличено)"
        court = base.anonymize(match.group(1)).strip()
        return re.sub(r"\s+", " ", court)
    return "Суд (обезличено)"


def safe_court(text: str) -> str:
    """Поле court обязательно проходит проверку на персональные данные.

    Раньше find_leaks применялся только к частям решения, а манифест
    с судьёй писался мимо проверки — рецензент поймал фамилию судьи в
    опубликованном деле. Не прошло проверку — судья не называется.
    """
    court = court_of(text)
    if base.find_leaks(court):
        return "Суд (обезличено)"
    return court


def pick_cases(documents: list[str], count: int) -> list[tuple[int, str]]:
    """Отобрать дела для демонстрации."""
    scored: list[tuple[int, int, str]] = []
    for index, text in enumerate(documents):
        score = score_candidate(text)
        if score >= 9:
            scored.append((score, index, text))
    scored.sort(key=lambda item: (-item[0], item[1]))

    chosen: list[tuple[int, str]] = []
    used: list[str] = []
    for score, index, text in scored:
        subject = subject_of(text)
        if used.count(subject) >= SUBJECT_LIMIT:
            continue
        chosen.append((index, text))
        used.append(subject)
        if len(chosen) >= count:
            break
    return chosen


def claim_amount_of(text: str) -> float:
    """Сумма иска из текста требований."""
    for candidate in sorted(
        {
            match.replace(" ", "")
            for match in re.findall(r"\d[\d\s]{2,}\s*руб", text, re.I)
        }
    ):
        digits = re.sub(r"[^\d]", "", candidate)
        if digits:
            return float(digits)
    return 0.0


def write_case(slug: str, parts: dict[str, str], court: str) -> dict[str, Any]:
    """Записать дело на диск и вернуть его описание."""
    case_dir = REAL_DIR / "cases" / slug
    case_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "00_case_info.txt": (
            "СВЕДЕНИЯ О ДЕЛЕ\n(по материалам дела)\n\n" + parts["header"]
        ),
        "01_claim.txt": (
            "ИСКОВОЕ ЗАЯВЛЕНИЕ ИСТЦА\n"
            "(изложение требований по материалам дела)\n\n" + parts["claim"]
        ),
        "02_response.txt": (
            "ВОЗРАЖЕНИЯ ОТВЕТЧИКА\n"
            "(изложение позиции ответчика по материалам дела)\n\n"
            + parts["defence"]
        ),
        "05_protocol.txt": (
            "ХОД СУДЕБНОГО ЗАСЕДАНИЯ\n(по материалам дела)\n\n"
            + parts["procedure"]
        ),
        "06_court_findings.txt": (
            "ОБСТОЯТЕЛЬСТВА, УСТАНОВЛЕННЫЕ СУДОМ\n"
            "(изложение по материалам дела)\n\n" + parts["findings"]
        ),
    }

    documents: list[dict[str, Any]] = []
    for name, content in files.items():
        text = content.strip()
        if not text:
            continue
        (case_dir / name).write_text(text + "\n", encoding="utf-8")
        documents.append(
            {
                "filename": name,
                "title": text.split("\n")[0],
                "document_type": DOCUMENT_TYPES.get(name, "OTHER"),
                "characters": len(text),
            }
        )

    reference = parts["operative"].strip()
    (case_dir / "court_decision_reference.txt").write_text(
        reference + "\n", encoding="utf-8"
    )

    manifest = {
        "warning": (
            "ОБЕЗЛИЧЕННОЕ РЕАЛЬНОЕ СУДЕБНОЕ РЕШЕНИЕ из открытого корпуса "
            "решений (Hugging Face: TryDotAtwo/russian-legal-ner). "
            "Персональные данные удалены скриптом."
        ),
        "case_number": slug.upper(),
        "court": court,
        "category": subject_of(reference),
        "hearing_date": "2012–2013",
        "plaintiff": "Организация",
        "defendant": "ФИО",
        "claim_amount": claim_amount_of(parts["claim"]),
        "documents": documents,
    }
    (case_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"manifest": manifest, "reference": reference}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Собрать дела из корпуса")
    parser.add_argument("--count", type=int, default=10, help="сколько дел")
    parser.add_argument(
        "--parquet", default=str(base.DEFAULT_PARQUET), help="путь к корпусу"
    )
    args = parser.parse_args(argv)

    parquet = Path(args.parquet)
    if not parquet.exists():
        base.download_parquet(parquet)

    documents = load_documents(parquet)
    print(f"решений в корпусе: {len(documents)}")

    chosen = pick_cases(documents, args.count)
    print(f"кандидатов отобрано: {len(chosen)}")
    if not chosen:
        print("ОШИБКА: подходящих решений не нашлось")
        return 1

    cases: list[dict[str, Any]] = []
    skipped = 0
    for number, (source_index, raw) in enumerate(chosen, start=1):
        parts = split_decision(raw)
        if not parts or not parts.get("operative"):
            skipped += 1
            continue

        cleaned = {key: anonymize(value) for key, value in parts.items()}
        leaks: list[str] = []
        for key, value in cleaned.items():
            leaks.extend(f"{key}: {leak}" for leak in find_leaks(value))
        if leaks:
            skipped += 1
            print(f"   пропущено (персональные данные): {leaks[0][:70]}")
            continue

        slug = f"real-{number:02d}"
        written = write_case(slug, cleaned, safe_court(raw))
        manifest = written["manifest"]
        cases.append(
            {
                "slug": slug,
                "case_number": manifest["case_number"],
                "court": manifest["court"],
                "category": manifest["category"],
                "claim_amount": manifest["claim_amount"],
                "documents": len(manifest["documents"]),
                "court_decision_reference": written["reference"],
                "source_index": source_index,
            }
        )
        print(
            f"   {slug}: {manifest['category']}, истец просит "
            f"{manifest['claim_amount']:.0f} руб., документов "
            f"{len(manifest['documents'])}"
        )

    if not cases:
        print("ОШИБКА: ни одно дело не прошло проверку")
        return 1

    index = {
        "source": (
            "TryDotAtwo/russian-legal-ner — открытый корпус судебных "
            "решений на Hugging Face"
        ),
        "anonymised": (
            "Тексты обезличены scripts/build_real_demo.py: фамилии, "
            "инициалы, названия организаций и номера дел заменены. "
            "Резолютивная часть суда приводится отдельно — для сравнения "
            "с проектом системы."
        ),
        "cases": cases,
    }
    (REAL_DIR / "cases").mkdir(parents=True, exist_ok=True)
    (REAL_DIR / "cases" / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"дел записано: {len(cases)}, пропущено: {skipped}\n"
        f"указатель: {REAL_DIR / 'cases' / 'index.json'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())