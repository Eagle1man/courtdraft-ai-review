"""Интерфейс провайдера эмбеддингов (п.5, п.53).

Требование ТЗ: система обязана стартовать и работать при отсутствии
embedding-модели, сообщая о degraded-режиме. Поэтому провайдер умеет
отвечать недоступностью, не бросая исключений на старте.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class EmbeddingStatus(StrEnum):
    """Состояние провайдера эмбеддингов."""

    READY = "ready"
    UNAVAILABLE = "unavailable"
    MOCK = "mock"


class Embedding(BaseModel):
    """Вектор вместе с provenance (п.12).

    Хранить источник обязательно: без него нельзя показать
    «источник утверждения» в интерфейсе.
    """

    vector: list[float]
    chunk_id: str
    document_id: str
    filename: str = ""
    document_type: str = ""
    page: int | None = None
    paragraph: int | None = None
    character_start: int | None = None
    character_end: int | None = None
    text: str = ""
    score: float | None = Field(default=None, description="Релевантность после поиска")


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Протокол эмбеддингов.

    Реализации: MockEmbeddingProvider, LocalEmbeddingProvider.
    """

    name: str

    @property
    def status(self) -> EmbeddingStatus:
        """Текущее состояние (для /api/health и UI)."""
        ...

    @property
    def dimension(self) -> int:
        """Размерность вектора."""
        ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Построить векторы для пачки текстов."""
        ...

    async def health(self) -> bool:
        """Готов ли провайдер к работе."""
        ...
