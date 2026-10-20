"""Демонстрационное дело: раздача синтетических материалов (Фаза 9, п.40, п.62).

Зачем это в API, а не только в скриптах: без него интерфейс нельзя
показать человеку, который никогда не запускал конвейер вручную. Один
клик создаёт дело, загружает в него материалы и запускает формирование
проекта — весь путь до первого текста занимает одну минуту.

Все данные синтетические. Отдача помечена в манифесте и в каждом ответе:
синтетическое дело не должно быть возможно спутать с настоящим.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import PlainTextResponse

from app.config import Settings, get_settings

router = APIRouter(prefix="/api/demo", tags=["demo"])


def _demo_dir(cfg: Settings) -> Path:
    return cfg.demo_dir


@router.get("/manifest")
async def get_manifest() -> dict[str, Any]:
    """GET /api/demo/manifest — описание демонстрационного дела.

    Ответ помечен как синтетический: интерфейс показывает эту пометку
    пользователю, а не прячет её в код страницы.
    """
    cfg = get_settings()
    path = _demo_dir(cfg) / "manifest.json"
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Демонстрационные материалы не найдены. "
                "Создайте их командой: python scripts/make_demo_case.py"
            ),
        )

    parsed: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return parsed


@router.get("/{filename}", response_class=PlainTextResponse)
async def get_demo_file(filename: str) -> PlainTextResponse:
    """GET /api/demo/{filename} — текст одного демонстрационного документа.

    Имя файла проверяется по списку из манифеста, а не «как пришло»:
    иначе через эту ручку можно было бы прочитать любой файл на диске,
    указав вместо имени `../../.env`.
    """
    cfg = get_settings()
    manifest_path = _demo_dir(cfg) / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Демонстрационные материалы не найдены.",
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    allowed = {
        str(entry.get("filename"))
        for entry in manifest.get("documents", [])
        if isinstance(entry, dict)
    }

    if filename not in allowed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Такого документа нет в демонстрационном деле.",
        )

    path = _demo_dir(cfg) / filename
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл демонстрационного дела отсутствует на диске.",
        )

    return PlainTextResponse(
        path.read_text(encoding="utf-8"),
        headers={"X-Synthetic-Data": "true"},
    )
