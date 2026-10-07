"""Локальный провайдер эмбеддингов для машины с RTX 3050 (п.3, п.53).

Использует модель через Ollama-совместимый HTTP-интерфейс.

Ключевое требование (п.53): если модель недоступна, провайдер НЕ падает,
а переходит в состояние unavailable. Приложение продолжает работать
в degraded-режиме и сообщает об этом в /api/health и в UI.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Sequence

import httpx

from app.embeddings.base import EmbeddingStatus

logger = logging.getLogger(__name__)


class EmbeddingsUnavailableError(RuntimeError):
    """Модель эмбеддингов недоступна.

    Вызывающий код должен переходить в degraded-режим, а не падать:
    backend обязан стартовать на машине без GPU.
    """


class LocalEmbeddingProvider:
    """Реальные эмбеддинги через Ollama.

    Состояние (READY / UNAVAILABLE) определяется лениво и кэшируется,
    чтобы не опрашивать модель на каждый вызов health.
    """

    name = "local"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        dimension: int = 1024,
        timeout_sec: int = 60,
        batch_size: int = 16,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dimension = dimension
        self._timeout = timeout_sec
        self._batch_size = max(1, batch_size)
        self._status = EmbeddingStatus.UNAVAILABLE
        self._lock = asyncio.Lock()

    @property
    def status(self) -> EmbeddingStatus:
        return self._status

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Построить векторы батчами (п.54 — ограничение памяти)."""
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = list(texts[start : start + self._batch_size])
            vectors.extend(await self._embed_batch(batch))

        return vectors

    async def health(self) -> bool:
        """Проверить доступность модели."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self._base_url}/api/tags")
                response.raise_for_status()
                names = {m.get("name", "") for m in response.json().get("models", [])}
        except httpx.HTTPError:
            await self._mark(EmbeddingStatus.UNAVAILABLE)
            return False

        base = self._model.split(":")[0]
        ready = any(n == self._model or n.split(":")[0] == base for n in names)
        await self._mark(EmbeddingStatus.READY if ready else EmbeddingStatus.UNAVAILABLE)
        return ready

    async def _embed_batch(self, batch: Sequence[str]) -> list[list[float]]:
        """Один запрос embeddings к Ollama."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/api/embed",
                    json={"model": self._model, "input": list(batch)},
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, KeyError) as exc:
            await self._mark(EmbeddingStatus.UNAVAILABLE)
            raise EmbeddingsUnavailableError(
                f"Модель эмбеддингов {self._model} недоступна ({exc}). "
                "Система работает в degraded-режиме."
            ) from exc

        vectors = data.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(batch):
            await self._mark(EmbeddingStatus.UNAVAILABLE)
            raise EmbeddingsUnavailableError(
                f"Ollama вернула {len(vectors) if isinstance(vectors, list) else 'нет'} "
                f"векторов вместо {len(batch)}"
            )

        # Размерность может отличаться от заявленной (другая модель).
        # Приводим к ожидаемой: иначе Qdrant отвергнет точки.
        normalised = [self._fit_dimension(v) for v in vectors]
        await self._mark(EmbeddingStatus.READY)
        return normalised

    def _fit_dimension(self, vector: object) -> list[float]:
        """Привести вектор к ожидаемой размерности.

        Обрезка или дополнение нулями. Не идеально, но лучше, чем упасть:
        размерность вектора — свойство индекса, а не повод блокировать работу.
        """
        values = [float(v) for v in vector] if isinstance(vector, list) else []
        if len(values) == self._dimension:
            return values
        if len(values) > self._dimension:
            return values[: self._dimension]
        return values + [0.0] * (self._dimension - len(values))

    async def _mark(self, status: EmbeddingStatus) -> None:
        """Обновить состояние, логируя переход в UNAVAILABLE."""
        async with self._lock:
            was_ready = self._status is EmbeddingStatus.READY
            if status is EmbeddingStatus.UNAVAILABLE and was_ready:
                logger.warning(
                    "Embedding provider unavailable. System is running in degraded/mock mode."
                )
            self._status = status


class HashEmbeddingProvider:
    """Резервный провайдер на случай недоступности реальной модели.

    Используется, когда EMBEDDINGS_OPTIONAL=true и локальная модель
    не поднялась: система продолжает работать, RAG остаётся функциональным
    в тестовом режиме, а /api/health показывает degraded.
    """

    name = "hash-fallback"

    def __init__(self, dimension: int = 1024) -> None:
        self._dimension = dimension

    @property
    def status(self) -> EmbeddingStatus:
        return EmbeddingStatus.UNAVAILABLE

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def health(self) -> bool:
        return False

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256((text or "").encode("utf-8")).digest()
        vector = [0.0] * self._dimension
        for i in range(min(64, len(text or "") // 24 + 1)):
            value = digest[i % len(digest)]
            vector[value % self._dimension] += 1.0 if value % 2 == 0 else -1.0
        return vector
