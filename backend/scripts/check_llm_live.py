"""Проверить локальную модель на живом вызове: здоровье, текст, JSON.

Отличие от scripts/check_ollama.py: тот только перечисляет реестр моделей,
а этот генерирует настоящий ответ провайдером приложения — ровно так, как
его вызывает конвейер. Именно такая проверка нужна перед демонстрацией:
модель может стоять в реестре и при этом не отвечать на запрос формата,
который ждёт агент.

Отчёт пишется в UTF-8-файл: консоль Windows портит кириллицу.

Запуск:
    .venv\\Scripts\\python.exe -X utf8 scripts\\check_llm_live.py
    .venv\\Scripts\\python.exe -X utf8 scripts\\check_llm_live.py --quick
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.llm import build_llm_provider  # noqa: E402
from app.llm.base import LLMMessage, LLMRequest  # noqa: E402

OUT = Path(r"C:\Users\diorl\AppData\Local\Temp\opencode\llm_live_check.txt")


async def run(quick: bool) -> tuple[list[str], int]:
    """Собрать результат проверки. Запись файла — в main, синхронно."""
    lines: list[str] = []
    provider = build_llm_provider()
    lines.append(f"провайдер: {provider.name}")
    lines.append(f"модель: {getattr(provider, '_model', '—')}")

    if not await provider.health():
        lines.append("ЗДОРОВЬЕ: НЕТ — Ollama недоступна или модели нет в реестре")
        return lines, 1
    lines.append("ЗДОРОВЬЕ: да")

    # 1. Обычный текст: тот же вызов, что делает агент для раздела.
    request = LLMRequest(
        messages=[
            LLMMessage(
                role="system",
                content="Ты — помощник судьи. Отвечай кратко и по существу.",
            ),
            LLMMessage(
                role="user",
                content=(
                    "Напиши раздел «Мотивы принятия решения» решения суда. "
                    "Дело № А-123. Истец просит взыскать 5 000 руб. по договору "
                    "поставки. Материалы дела: договор поставки, расписка о "
                    "получении 5 000 руб."
                ),
            ),
        ],
        temperature=0.1,
        max_tokens=200,
    )
    response = await provider.generate(request)
    lines.append("")
    lines.append("— текст —")
    lines.append(
        f"модель: {response.model} · is_mock={response.is_mock} · "
        f"{response.latency_ms / 1000:.1f} с · "
        f"токенов: {response.usage.prompt_tokens}+{response.usage.completion_tokens}"
    )
    lines.append(response.text.strip()[:800])

    if quick:
        lines.append("")
        lines.append("(JSON-проверка пропущена: --quick)")
        return lines, 0

    # 2. JSON-режим: агенты разведки просят структурированный ответ.
    #    Проверяется именно он, потому что модель, дающая красивый текст,
    #    часто не умеет отдавать валидный JSON — и агент получает default.
    json_request = LLMRequest(
        messages=[
            LLMMessage(
                role="system",
                content=(
                    "Отвечай ТОЛЬКО валидным JSON вида "
                    '{"court": "...", "sum": "..."}'
                ),
            ),
            LLMMessage(
                role="user",
                content="Суд: районный суд. Сумма иска: 5 000 руб.",
            ),
        ],
        temperature=0.0,
        max_tokens=120,
        json_mode=True,
    )
    parsed = await provider.generate_json(json_request, default={"error": "не разобран"})
    lines.append("")
    lines.append("— JSON —")
    lines.append(str(parsed)[:400])

    return lines, 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Живая проверка модели")
    parser.add_argument(
        "--quick", action="store_true", help="только текст, без JSON-проверки"
    )
    args = parser.parse_args()
    lines, code = asyncio.run(run(args.quick))
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"записано: {OUT}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
