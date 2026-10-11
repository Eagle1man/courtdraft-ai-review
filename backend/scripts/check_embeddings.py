"""Проверить, что bge-m3 отдаёт эмбеддинги нужной размерности.

Проверяется не только «модель отвечает», но и три вещи, на которых
ломается весь поиск:

1. размерность вектора совпадает с EMBEDDING_DIM из настроек;
2. векторы для разных текстов РАЗНЫЕ (иначе индекс бессмыслен);
3. похожие по смыслу тексты ближе друг к другу, чем непохожие —
   ради этого эмбеддинги и нужны.

Запуск:
    .venv\\Scripts\\python.exe -X utf8 scripts\\check_embeddings.py
"""

from __future__ import annotations

# S310 — весь смысл файла в обращении к локальному сервису Ollama по
# адресу с постоянной схемой http. Схема не берётся извне.
# ruff: noqa: S310
import json
import math
import urllib.request
from pathlib import Path

OUT = Path(r"C:\Users\diorl\AppData\Local\Temp\opencode\embeddings_check.txt")

BASE = "http://127.0.0.1:11434/api/embed"
MODEL = "bge-m3"
EXPECTED_DIM = 1024

# Три текста на русском из одной предметной области и один посторонний.
# Если модель русская, похожие тексты обязаны быть ближе друг к другу.
TEXTS = [
    "Истец требует взыскать задолженность по договору поставки в размере 150000 рублей.",
    "По договору поставки ответчик не оплатил товар, образовался долг 150000 рублей.",
    "В исковом заявлении указана цена иска 150000 рублей и госпошлина 5100 рублей.",
    "Рецепт приготовления борща: свёкла, капуста, мясо, вода, соль.",
]


def embed(texts: list[str]) -> list[list[float]]:
    body = json.dumps({"model": MODEL, "input": texts}).encode("utf-8")
    request = urllib.request.Request(BASE, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.loads(response.read())["embeddings"]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def main() -> int:
    lines: list[str] = []
    ok = True

    try:
        vectors = embed(TEXTS)
    except Exception as exc:  # noqa: BLE001
        OUT.write_text(f"ошибка запроса эмбеддингов: {exc}\n", encoding="utf-8")
        print(f"записано: {OUT}")
        return 1

    dim = len(vectors[0])
    lines.append(f"модель: {MODEL}")
    lines.append(f"векторов: {len(vectors)}")
    lines.append(f"размерность: {dim} (ожидалось {EXPECTED_DIM})")

    if dim != EXPECTED_DIM:
        lines.append("РАЗМЕРНОСТЬ НЕ СОВПАДАЕТ — индекс создать нельзя")
        ok = False
    else:
        lines.append("размерность совпадает")

    unique = len({tuple(round(x, 6) for x in v) for v in vectors})
    lines.append(f"различных векторов: {unique} из {len(vectors)}")
    if unique != len(vectors):
        lines.append("ВЕКТОРЫ ПОВТОРЯЮТСЯ — индекс не имеет смысла")
        ok = False
    else:
        lines.append("векторы различаются")

    lines.append("")
    lines.append("близость по смыслу (косинус, больше — ближе):")
    pairs = [
        (0, 1, "два варианта одного требования — ДОЛЖНЫ быть близки"),
        (0, 2, "иск и цена иска — близки"),
        (0, 3, "юридический текст и рецепт — ДОЛЖНЫ быть далеки"),
    ]
    for i, j, comment in pairs:
        value = cosine(vectors[i], vectors[j])
        lines.append(f"  {value:+.3f}  [{i}] и [{j}]  {comment}")

    close = cosine(vectors[0], vectors[1])
    far = cosine(vectors[0], vectors[3])
    if close > far:
        lines.append("")
        lines.append("смысл улавливается: похожее ближе, непохожее дальше")
    else:
        lines.append("")
        lines.append("ПРОВАЛ: похожие тексты не ближе непохожих")
        ok = False

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"записано: {OUT}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
