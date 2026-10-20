"""Детерминированный провайдер эмбеддингов для режима без GPU (п.6, п.39).

Позволяет прогнать весь RAG-конвейер на ноутбуке 8 GB без модели эмбеддингов.

Важное свойство: вектор детерминирован по тексту. Это значит, что поиск
в MOCK-режиме воспроизводим — метрики Recall@5 и MRR измеряют работу
конвейера, а не случайность модели.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from app.embeddings.base import EmbeddingStatus


class MockEmbeddingProvider:
    """Эмбеддинги без модели: вектор выводится из хэша текста.

    Это не семантика — это воспроизводимая проекция. Её достаточно, чтобы
    проверить: правильно ли строятся индексы, фильтруются ли метаданные,
    работает ли RRF, считаются ли метрики. Реальную семантику даёт
    LocalEmbeddingProvider на машине с RTX 3050.
    """

    name = "mock"

    def __init__(self, dimension: int = 1024) -> None:
        if dimension <= 0:
            raise ValueError(f"dimension должен быть положительным, получено {dimension}")
        self._dimension = dimension

    @property
    def status(self) -> EmbeddingStatus:
        """Заглушка всегда готова."""
        return EmbeddingStatus.MOCK

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Построить векторы. Детерминированно и по батчам (п.54)."""
        return [self._vector_for(text) for text in texts]

    async def health(self) -> bool:
        return True

    def _vector_for(self, text: str) -> list[float]:
        """Собрать нормированный вектор из хэшей фрагментов текста.

        Берём симметричные хэши, чтобы близкие по хэшу фрагменты давали
        близкие векторы — иначе любой поиск в MOCK-режиме возвращал бы
        произвольный порядок и метрики были бы случайными.
        """
        normalized = (text or "").strip().lower()
        if not normalized:
            return [0.0] * self._dimension

        # Число «признаков» пропорционально длине текста, но ограничено,
        # чтобы длинные документы не давали тысячи признаков.
        feature_count = max(8, min(64, len(normalized) // 24))
        vector = [0.0] * self._dimension

        for i in range(feature_count):
            start = (i * len(normalized)) // feature_count
            end = max(start + 1, ((i + 1) * len(normalized)) // feature_count)
            feature = normalized[start:end]

            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimension
            # Знак из следующих байтов: иначе все признаки положительные
            # и косинусная близость вырождается.
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]
