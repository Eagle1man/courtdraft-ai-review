"""Проверка ссылок в документации.

Битая ссылка в README выглядит как небрежность и хуже отсутствия
ссылки вообще. Скрипт проверяет локальные пути и якоря.

Запуск:
    .venv\\Scripts\\python.exe scripts\\check_links.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$", re.MULTILINE)
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def slugify(heading: str) -> str:
    """Якорь в стиле GitHub."""
    text = heading.strip().lower()
    text = re.sub(r"[`*_]", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "-", text)
    return text.strip("-")


def anchors_of(path: Path) -> set[str]:
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8", errors="replace")
    text = FENCE_RE.sub("", text)
    return {slugify(h) for _, h in HEADING_RE.findall(text)}


def main() -> int:
    docs = sorted(
        p
        for p in ROOT.glob("**/*.md")
        if not any(
            part in p.parts
            for part in (".venv", "node_modules", ".git", "site")
        )
    )

    problems: list[str] = []
    checked = 0

    for doc in docs:
        text = doc.read_text(encoding="utf-8", errors="replace")
        # Код в блоках не считается ссылками.
        text = FENCE_RE.sub("", text)

        for label, target in MD_LINK_RE.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#!")):
                continue

            if target.startswith("#"):
                target_path, _, frag = doc, "", target[1:]
            elif "#" in target:
                raw, _, frag = target.partition("#")
                target_path = (doc.parent / raw).resolve()
            else:
                target_path, frag = (doc.parent / target).resolve(), ""

            checked += 1
            rel = target_path.relative_to(ROOT) if ROOT in target_path.parents else target_path

            if not target_path.exists():
                problems.append(f"{doc.name}: ссылка «{label}» → нет файла {rel}")
                continue

            if frag and target_path.suffix.lower() == ".md":
                if frag not in anchors_of(target_path):
                    problems.append(
                        f"{doc.name}: ссылка «{label}» → якорь #{frag} "
                        f"не найден в {rel.name}"
                    )

    print(f"файлов проверено: {len(docs)}")
    print(f"ссылок проверено: {checked}")
    print()

    if problems:
        print(f"БИТЫЕ ССЫЛКИ ({len(problems)}):")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("OK — все локальные ссылки и якоря на месте.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
