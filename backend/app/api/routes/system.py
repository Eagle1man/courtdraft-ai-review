"""Роутеры API.

Сейчас реализован /api/health и /api/info (Фаза 2). Остальные эндпоинты
из п.42 добавляются по фазам 3-10; здесь перечислены заглушки-константы,
чтобы клиент заранее знал ожидаемый контракт, но НЕ как рабочие ручки.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status

from app.config import Settings, get_settings
from app.db.bootstrap import MIGRATE_HINT, check_schema_drift
from app.schemas.health import ApiInfoResponse, HealthResponse
from app.services.health_service import build_health, build_info

router = APIRouter(prefix="/api", tags=["system"])


def settings_of(request: Request) -> Settings:
    """Настройки, с которыми собрано приложение.

    Берём из состояния приложения, а не из get_settings(): create_app()
    мог быть вызван с переопределениями, и проверка обязана это учитывать.
    """
    return getattr(request.app.state, "settings", None) or get_settings()


@router.get("/health", response_model=HealthResponse)
async def health(cfg: Settings = Depends(settings_of)) -> HealthResponse:
    """Состояние всех компонентов (п.38).

    Всегда отдаёт 200 с полным отчётом: клиенту нужно видеть, ЧТО именно
    не работает. HTTP-код оставлен для будущего readiness-режима
    (для оркестратора), но не для диагностики.
    """
    return await build_health(cfg)


@router.get("/info", response_model=ApiInfoResponse)
async def info(cfg: Settings = Depends(settings_of)) -> ApiInfoResponse:
    """Идентификация сервиса и текущий режим ИИ."""
    return build_info(cfg)


@router.get("/ready", include_in_schema=False)
async def ready(
    response: Response, cfg: Settings = Depends(settings_of)
) -> dict[str, object]:
    """Readiness для оркестратора.

    Возвращает 503, только если сломано то, что обязательно в текущем
    режиме. В режиме разработки отсутствие Ollama и эмбеддингов — не повод
    отказывать в готовности.

    Рассинхрон схемы БД тоже делает сервис неготовым: писать в таблицу
    с недостающей колонкой нельзя, и запросы будут паять по одному.
    """
    report = await build_health(cfg)
    payload: dict[str, object] = {"status": report.status}

    missing = await check_schema_drift()
    if missing:
        payload["schema_drift"] = missing
        payload["hint"] = MIGRATE_HINT

    if report.status == "ERROR" or missing:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        if report.status != "ERROR":
            payload["status"] = "SCHEMA_DRIFT"

    return payload
