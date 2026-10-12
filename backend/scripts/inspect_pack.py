"""Показать, как устроен пакет доказательств и где склеиваются требования.

Скрипт диагностический: он печатает элементы пакета с их категориями и
документами, а также результат склейки. Нужен, когда требование не
доходит до резолютивной части — видно, где оно рассыпалось.

Запуск:
    .venv\\Scripts\\python.exe -X utf8 scripts\\inspect_pack.py
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.agents.evidence_pack import EvidenceItem  # noqa: E402
from app.drafting.requirements import _join_claim  # noqa: E402

RESULT = pathlib.Path(r"D:\courtdraft-ai\data\demo\output\result.json")
OUT = pathlib.Path(
    r"C:\Users\diorl\AppData\Local\Temp\opencode\pack_inspect.txt"
)


def main() -> int:
    if not RESULT.exists():
        print(f"нет файла: {RESULT}")
        return 1

    data = json.loads(RESULT.read_text(encoding="utf-8"))
    items = data["evidence_pack"]["items"]

    # Имена полей в JSON отличаются от имён полей объекта EvidenceItem,
    # поэтому берётся первое подходящее: иначе диагностика падает на
    # отсутствующем ключе и не показывает ничего.
    def field(item: dict[str, object], *names: str) -> str:
        for name in names:
            if item.get(name):
                return str(item[name])
        return "?"

    lines: list[str] = [f"ЭЛЕМЕНТОВ: {len(items)}", ""]
    for index, item in enumerate(items):
        lines.append(
            f"{index:3} [{field(item, 'category'):18}] "
            f"{field(item, 'source_document', 'source'):24} "
            f"{field(item, 'text')[:90]}"
        )

    # Склейка работает с объектами EvidenceItem, а не со словарём из
    # JSON: на словаре она падала бы на обращении к .text.
    pack_items = [
        EvidenceItem(
            category=str(item.get("category", "")),
            text=str(item.get("text", "")),
            source_document=str(
                item.get("source_document") or item.get("source") or ""
            ),
            source_type=str(item.get("source_type", "")),
        )
        for item in items
    ]

    lines.append("")
    lines.append("=== СКЛЕЙКА ДЛЯ ПОЗИЦИИ 0 ===")
    lines.append(_join_claim(pack_items, 0)[:600])

    lines.append("")
    lines.append("=== СКЛЕЙКА ДЛЯ КАЖДОЙ ПОЗИЦИИ, ГДЕ ЕСТЬ ГЛАГОЛ ===")
    for index in range(len(pack_items)):
        text = pack_items[index].text
        if "зыска" in text or "ризнать" in text or "бязать" in text:
            joined = _join_claim(pack_items, index)  # type: ignore[arg-type]
            if len(joined) > len(text):
                lines.append(f"[{index}] {joined[:300]}")
                lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"записано: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
