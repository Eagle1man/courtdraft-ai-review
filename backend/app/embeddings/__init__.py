"""Фабрика провайдеров эмбеддингов.

Правило ТЗ п.53: отсутствие embedding-модели не должно мешать запуску.
Поэтому выбор провайдера никогда не бросает исключений — при любой
неудаче система возвращает работоспособный провайдер и остаётся
в degraded-режиме, о чём честно сообщает в /api/health.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.config import EmbeddingProviderName, Settings, get_settings
from app.embeddings.base import EmbeddingProvider
from app.embeddings.local import HashEmbeddingProvider, LocalEmbeddingProvider
from app.embeddings.mock import MockEmbeddingProvider

logger = logging.getLogger(__name__)


def build_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    """Создать провайдера эмбеддингов по настройкам."""
    cfg = settings or get_settings()

    if cfg.embedding_provider is EmbeddingProviderName.MOCK:
        return MockEmbeddingProvider(dimension=cfg.embedding_dim)

    if cfg.embedding_provider is EmbeddingProviderName.LOCAL:
        # Не поднимаем модель здесь: это блокировало бы старт на 8 ГБ.
        # Реальная доступность выясняется при первом embed()/health().
        return LocalEmbeddingProvider(
            base_url=cfg.ollama_base_url,
            model=cfg.embedding_model,
            dimension=cfg.embedding_dim,
            timeout_sec=cfg.ollama_timeout_sec,
            batch_size=cfg.embedding_batch_size,
        )

    return MockEmbeddingProvider(dimension=cfg.embedding_dim)


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    """Провайдер эмбеддингов для приложения."""
    return build_embedding_provider()


async def get_healthy_embedding_provider() -> EmbeddingProvider:
    """Провайдер, готовый к работе.

    Если локальная модель недоступна, а EMBEDDINGS_OPTIONAL=true —
    возвращает резервный провайдер вместо исключения (п.53).
    """
    provider = get_embedding_provider()

    if provider.name in {"mock", "hash-fallback"}:
        return provider

    if await provider.health():
        return provider

    cfg = get_settings()
    if cfg.embeddings_optional:
        logger.warning(
            "Embedding provider unavailable. "
            "System is running in degraded/mock mode."
        )
        return HashEmbeddingProvider(dimension=cfg.embedding_dim)

    # embeddings_optional=false — пользователь явно попросил строгий режим.
    raise RuntimeError(
        f"Embedding provider unavailable и EMBEDDINGS_OPTIONAL=false. "
        f"Запустите модель {cfg.embedding_model} через Ollama."
    )


def reset_embedding_provider_cache() -> None:
    """Сбросить кэш (для тестов)."""
    get_embedding_provider.cache_clear()
