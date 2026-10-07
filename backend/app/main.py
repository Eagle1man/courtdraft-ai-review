"""Точка входа FastAPI (Фаза 2).

Что уже работает:
  - приложение стартует без БД, без Qdrant и без модели эмбеддингов;
  - /api/health различает REQUIRED и NOT REQUIRED компоненты;
  - /api/docs открывается.

Модель и эмбеддинги не загружаются при старте — это принципиально для
машины 8 GB без GPU (п.50).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import system
from app.config import Settings, get_settings
from app.services.health_service import DISCLAIMER, VERSION

logging.basicConfig(
    level=getattr(logging, get_settings().log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("courtdraft")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Собрать приложение FastAPI."""
    cfg = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Каталоги данных создаются при старте, а не вручную:
        # отсутствие каталога не должно быть причиной падения.
        cfg.ensure_dirs()
        logger.info(
            "CourtDraft AI %s стартует: env=%s llm=%s embeddings=%s",
            VERSION,
            cfg.app_env.value,
            cfg.llm_provider.value,
            cfg.embedding_provider.value,
        )
        if not cfg.is_real_mode:
            logger.info("MOCK-режим: реальная LLM не вызывается (это штатно для разработки)")
        yield
        logger.info("CourtDraft AI остановлен")

    app = FastAPI(
        title="CourtDraft AI",
        version=VERSION,
        description=(
            "Локальная подготовка проекта судебного акта.\n\n"
            f"⚠️ {DISCLAIMER}"
        ),
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    # Настройки кладём в состояние приложения: роутеры и health-check должны
    # видеть ту конфигурацию, с которой приложение собрано, а не глобальный .env.
    app.state.settings = cfg

    # Только локальные Origins (п.44): никакого облака.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(system.router)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        """Корень: указать, где документация."""
        return {
            "name": "CourtDraft AI",
            "version": VERSION,
            "docs": "/docs",
            "health": "/api/health",
        }

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        """Единый формат необработанных ошибок.

        Текст исключения возвращается в ответе только в debug-режиме:
        в сообщениях об ошибках не должно быть содержимого судебных документов.
        """
        logger.exception("Необработанная ошибка при обработке %s", request.url.path)
        detail = str(exc) if cfg.debug else "Внутренняя ошибка сервиса"
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": detail},
        )

    return app


app = create_app()
