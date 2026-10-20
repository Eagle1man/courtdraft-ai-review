"""Проверить, какие модели видит Ollama и где он их держит.

Скрипт нужен по двум причинам: консоль PowerShell на этой машине
искажает кириллицу, а вызов через -c с кириллическими строками внутри
ломается ещё и кавычками. Поэтому проверка пишет в файл UTF-8.

Запуск:
    .venv\\Scripts\\python.exe -X utf8 scripts\\check_ollama.py
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

OUT = Path(r"C:\Users\diorl\AppData\Local\Temp\opencode\ollama_state.txt")
MODELS_DIR = Path(os.environ.get("OLLAMA_MODELS", "")) if os.environ.get("OLLAMA_MODELS") else None


def main() -> int:
    lines = []

    lines.append(f"OLLAMA_MODELS в окружении: {os.environ.get('OLLAMA_MODELS', '— НЕ ЗАДАН —')}")

    if MODELS_DIR and MODELS_DIR.exists():
        total = sum(f.stat().st_size for f in MODELS_DIR.rglob("*") if f.is_file())
        lines.append(f"каталог моделей: {MODELS_DIR} ({total / 1024**3:.1f} ГБ)")
    else:
        lines.append(f"каталог моделей: {MODELS_DIR or 'по умолчанию'} — НЕ НАЙДЕН")

    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=15) as r:
            data = json.loads(r.read())
    except Exception as exc:  # noqa: BLE001
        lines.append(f"сервер не отвечает: {exc}")
        OUT.write_text("\n".join(lines), encoding="utf-8")
        print(f"записано: {OUT}")
        return 1

    lines.append(f"моделей в реестре: {len(data.get('models', []))}")
    for model in data.get("models", []):
        size_mb = model.get("size", 0) / 1024**2
        lines.append(f"  {model['name']}  {size_mb:.0f} МБ")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"записано: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
