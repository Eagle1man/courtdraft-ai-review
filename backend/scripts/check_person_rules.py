"""Проверка новых правил на настоящем тексте из прогона модели.

Отдельный файл, а не тест: здесь важно увидеть сами находки глазами,
а не только их количество. Тесты проверяют, что правило срабатывает;
этот скрипт показывает, на что оно похоже в применении.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.agents.evidence_pack import build_evidence_pack  # noqa: E402
from app.ingestion.extract import extract_text, guess_document_type  # noqa: E402
from app.verification.persons import (  # noqa: E402
    check_composition,
    check_persons,
    check_roles,
    known_persons,
)

DEMO = BACKEND.parent / "data" / "demo"


class _Doc:
    def __init__(self, name: str, text: str) -> None:
        self.filename = name
        self.text = text
        self.document_type = guess_document_type(name, text)
        self.page_count = 1
        self.id = name


def build_pack():  # noqa: ANN201 - пакет доказательств
    docs = []
    for path in sorted(DEMO.glob("*.txt")):
        extracted = extract_text(path.name, path.read_bytes())
        docs.append(_Doc(path.name, extracted.text))
    return build_evidence_pack("DEMO-001", "Демонстрационный суд", "договорные споры", docs)


def report(label: str, text: str, section: str, pack) -> bool:  # noqa: ANN001
    print()
    print(f"--- {label} ---")
    persons = check_persons(text, section, pack) + check_composition(text, section, pack)
    roles = check_roles(text, section, pack)

    if not persons and not roles:
        print("   замечаний нет")
        return False

    for finding in persons:
        print(f"   ПЕРСОНА  {finding.reason}")
    for finding in roles:
        print(f"   РОЛЬ     {finding.detail}")
    return True


def main() -> int:
    pack = build_pack()
    print("Персоны, найденные в материалах дела:")
    for person in sorted(known_persons(pack)):
        print(f"   {person}")

    # Текст взят из реального прогона модели на DEMO-001.
    found_bad = report(
        "текст из прогона: выдуманы судья и состав суда",
        "Суд: Демонстрационный районный суд г. Образцова\n"
        "Дело № DEMO-001\n"
        "Состав суда: Прокурор, судья, секретарь\n"
        "Судья: Иванов Иван Иванович\n"
        "Истец Образцов Пётр Петрович обратился в суд с иском.",
        "Вводная часть",
        pack,
    )

    found_roles = report(
        "текст из прогона: роли сторон перепутаны",
        "1. Образцов Пётр Петрович обязуется в течение месяца со дня вручения "
        "решения оплатить сумму 150000 рублей.\n"
        "2. Суд взыскивает с истца задолженность в размере 30000 рублей.",
        "РЕШИЛ",
        pack,
    )

    clean = report(
        "корректный текст должен остаться чистым",
        "Суд: Демонстрационный районный суд г. Образцова.\n"
        "Истец: Образцов Пётр Петрович.\n"
        "Ответчик: Фирма «Вымышленная Строй».\n"
        "Суд взыскивает с ответчика в пользу истца 150000 рублей.",
        "Описательная часть",
        pack,
    )

    print()
    print("=" * 70)
    if not found_bad:
        print("ПРОВАЛ: выдуманная персона не обнаружена")
        return 1
    if not found_roles:
        print("ПРОВАЛ: переставленные роли не обнаружены")
        return 1
    if clean:
        print("ПРОВАЛ: корректный текст помечен замечаниями — ложное срабатывание")
        return 1

    print("Правила работают: выдумки находятся, корректный текст не трогается.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
